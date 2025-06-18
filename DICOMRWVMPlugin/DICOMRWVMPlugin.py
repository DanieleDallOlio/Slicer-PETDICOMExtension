import os
import sys as SYS
from __main__ import vtk, qt, ctk, slicer
from DICOMLib import DICOMPlugin
from DICOMLib import DICOMLoadable
import logging

if slicer.app.majorVersion >= 5 or (slicer.app.majorVersion == 4 and slicer.app.minorVersion >= 11):
  import pydicom
else:
  import dicom

import DICOMLib

import math as math

class CodedValueTuple:
  def __init__(self, CodeValue=None, CodeMeaning=None, CodingSchemeDesignator=None):
    self.CodeValue = CodeValue
    self.CodeMeaning = CodeMeaning
    self.CodingSchemeDesignator = CodingSchemeDesignator

  def getDictionary(self):
    return {"CodeValue":self.CodeValue, "CodeMeaning":self.CodeMeaning, "CodingSchemeDesignator":self.CodingSchemeDesignator}

#
# This is the plugin to handle Real World Value Mapping objects
# from DICOM files into MRML nodes.  It follows the DICOM module's
# plugin architecture.
#

class DICOMRWVMPluginClass(DICOMPlugin):
  """ PET specific interpretation code
  """

  def __init__(self):
    super(DICOMRWVMPluginClass,self).__init__()
    self.epsilon = 0.01
    self.loadType = "Real World Value Mapping Plugin"
    self.tags['patientID'] = "0010,0020"
    self.tags['patientName'] = "0010,0010"
    self.tags['patientBirthDate'] = "0010,0030"
    self.tags['patientSex'] = "0010,0040"
    self.tags['patientHeight'] = "0010,1020"
    self.tags['patientWeight'] = "0010,1030"

    self.tags['referencedSeriesSequence'] = "0008,1115"

    self.tags['contentTime'] = "0008,0033"
    self.tags['seriesTime'] = "0008,0031"
    self.tags['triggerTime'] = "0018,1060"
    self.tags['diffusionGradientOrientation'] = "0018,9089"
    self.tags['imageOrientationPatient'] = "0020,0037"
    self.tags['numberOfFrames'] = "0028,0008"

    self.tags['seriesDescription'] = "0008,103e"
    self.tags['seriesModality'] = "0008,0060"
    self.tags['seriesInstanceUID'] = "0020,000E"
    self.tags['sopInstanceUID'] = "0008,0018"

    self.tags['studyInstanceUID'] = "0020,000D"
    self.tags['studyDate'] = "0008,0020"
    self.tags['studyTime'] = "0008,0030"
    self.tags['studyID'] = "0020,0010"

    self.tags['rows'] = "0028,0010"
    self.tags['columns'] = "0028,0011"
    self.tags['spacing'] = "0028,0030"
    self.tags['position'] = "0020,0032"
    self.tags['orientation'] = "0020,0037"
    self.tags['pixelData'] = "7fe0,0010"

    self.tags['referencedImageRWVMappingSeq'] = "0040,9094"

    self.scalarVolumePlugin = slicer.modules.dicomPlugins['DICOMScalarVolumePlugin']()


  def __getDirectoryOfImageSeries(self, sopInstanceUID):
    f = slicer.dicomDatabase.fileForInstance(sopInstanceUID)
    return os.path.dirname(f)

  def __getSeriesInformation(self,seriesFiles,dicomTag):
    if seriesFiles:
      return  slicer.dicomDatabase.fileValue(seriesFiles[0],dicomTag)


  def examine(self,fileLists):
    """ Returns a list of DICOMLoadable instances
    corresponding to ways of interpreting the
    fileLists parameter.
    """
    loadables = []
    # get from cache or create new loadables
    for fileList in fileLists:
      cachedLoadables = self.getCachedLoadables(fileList)
      if cachedLoadables:
        loadables += cachedLoadables
      else:
        if slicer.dicomDatabase.fileValue(fileList[0],self.tags['seriesModality']) == "RWV":
          if len(fileList)>1:
            # TODO: look into logging using ctkFileLog
            print('Warning: series contains more than 1 RWV instance! Only first one is considered!')
          loadablesForFiles = self.getLoadablesFromRWVMFile(fileList[0])
          loadables += loadablesForFiles
          self.cacheLoadables(fileList[0],loadablesForFiles)

    return loadables

  def getLoadablesFromRWVMFile(self, file):
    rwvLoadable = DICOMLib.DICOMLoadable()
    rwvLoadable.files.append(file)
    rwvLoadable.patientName = self.__getSeriesInformation(rwvLoadable.files, self.tags['patientName'])
    rwvLoadable.patientID = self.__getSeriesInformation(rwvLoadable.files, self.tags['patientID'])
    rwvLoadable.studyDate = self.__getSeriesInformation(rwvLoadable.files, self.tags['studyDate'])
    if slicer.app.majorVersion >= 5 or (slicer.app.majorVersion == 4 and slicer.app.minorVersion >= 11):
      dicomFile = pydicom.dcmread(file)
    else:
      dicomFile = dicom.read_file(file)
    rwvmSeq = dicomFile.ReferencedImageRealWorldValueMappingSequence[0].RealWorldValueMappingSequence
    unitsSeq = rwvmSeq[0].MeasurementUnitsCodeSequence
    rwvLoadable.name = rwvLoadable.patientName + ' ' + self.convertStudyDate(rwvLoadable.studyDate) + ' ' + unitsSeq[0].CodeMeaning
    rwvLoadable.unitName = unitsSeq[0].CodeMeaning

    (quantity,units) = self.getQuantityAndUnitsFromDICOM(dicomFile)

    rwvLoadable.quantity = quantity
    rwvLoadable.units = units

    rwvLoadable.tooltip = rwvLoadable.name
    rwvLoadable.selected = True
    rwvLoadable.confidence = 0.90
    return [rwvLoadable]

  def getLoadablePetSeriesFromRWVMFile(self, file):
    """ Returns DICOMLoadable instances associated with an RWVM object."""

    newLoadables = []
    if slicer.app.majorVersion >= 5 or (slicer.app.majorVersion == 4 and slicer.app.minorVersion >= 11):
      dicomFile = pydicom.dcmread(file)
    else:
      dicomFile = dicom.read_file(file)
    if dicomFile.Modality == "RWV":
      refRWVMSeq = dicomFile.ReferencedImageRealWorldValueMappingSequence
      refSeriesSeq = dicomFile.ReferencedSeriesSequence
      if refRWVMSeq:
        # May have more than one RWVM value, create loadables for each
        for item in refRWVMSeq:
          rwvLoadable = DICOMLib.DICOMLoadable()
          # Get the referenced files from the database
          refImageSeq = item.ReferencedImageSequence
          instanceFiles = []
          for instance in refImageSeq:
            uid = instance.ReferencedSOPInstanceUID
            if uid:
              instanceFiles += [slicer.dicomDatabase.fileForInstance(uid)]
          # Get the Real World Values
          rwvLoadable.files = instanceFiles
          rwvLoadable.rwvFile = file
          rwvLoadable.patientName = self.__getSeriesInformation(rwvLoadable.files, self.tags['patientName'])
          rwvLoadable.patientID = self.__getSeriesInformation(rwvLoadable.files, self.tags['patientID'])
          rwvLoadable.studyDate = self.__getSeriesInformation(rwvLoadable.files, self.tags['studyDate'])

          rwvmSeq = item.RealWorldValueMappingSequence
          unitsSeq = rwvmSeq[0].MeasurementUnitsCodeSequence
          rwvLoadable.name = rwvLoadable.patientName + ' ' + self.convertStudyDate(rwvLoadable.studyDate) + ' ' + unitsSeq[0].CodeMeaning
          rwvLoadable.tooltip = rwvLoadable.name

          (quantity,units) = self.getQuantityAndUnitsFromDICOM(dicomFile)

          rwvLoadable.quantity = quantity
          rwvLoadable.units = units

          rwvLoadable.confidence = 0.90
          rwvLoadable.selected = True # added by CB
          rwvLoadable.slope = rwvmSeq[0].RealWorldValueSlope
          rwvLoadable.referencedSeriesInstanceUID = refSeriesSeq[0].SeriesInstanceUID

          # determine modality of referenced series
          refSeriesFiles = slicer.dicomDatabase.filesForSeries(refSeriesSeq[0].SeriesInstanceUID)
          if slicer.app.majorVersion >= 5 or (slicer.app.majorVersion == 4 and slicer.app.minorVersion >= 11):
            refSeriesFile0 = pydicom.dcmread(refSeriesFiles[0])
          else:
            refSeriesFile0 = dicom.read_file(refSeriesFiles[0])
          rwvLoadable.referencedModality = refSeriesFile0.Modality

          # add radiopharmaceutical info if PET
          if rwvLoadable.referencedModality == 'PT':
            print('Found Referenced PET series')
            ris = refSeriesFile0.RadiopharmaceuticalInformationSequence[0]
            try: # TODO Many DICOM series do not have radiopharmaceutical code sequence!
              rcs = ris.RadiopharmaceuticalCodeSequence
              if len(rcs) > 0:
                rwvLoadable.RadiopharmaceuticalCodeValue = rcs[0].CodeValue
            except AttributeError:
              print('WARNING: series does not have radiopharmaceutical code sequence.')
            try:
              rcs = ris.RadionuclideCodeSequence
              if len(rcs) > 0:
                rwvLoadable.RadionuclideCodeValue = rcs[0].CodeValue
            except AttributeError:
              print('WARNING: Cannot find radionuclide info for PET Series.')

          self.sortLoadableSeriesFiles(rwvLoadable)
          newLoadables.append(rwvLoadable)

    return newLoadables

  def getQuantityAndUnitsFromDICOM(self, dicomObject):
    try:
      units = slicer.vtkCodedEntry()
      quantity = slicer.vtkCodedEntry()

      rwvmSeq = dicomObject.ReferencedImageRealWorldValueMappingSequence[0].RealWorldValueMappingSequence
      unitsSeq = rwvmSeq[0].MeasurementUnitsCodeSequence
      units.SetValueSchemeMeaning(unitsSeq[0].CodeValue, unitsSeq[0].CodingSchemeDesignator, unitsSeq[0].CodeMeaning)

      quantitySeq = rwvmSeq[0][0x0040,0x9220]
      for qsItem in quantitySeq:
        if qsItem.ConceptNameCodeSequence[0].CodeMeaning == "Quantity":
          concept = qsItem.ConceptCodeSequence[0]
          quantity.SetValueSchemeMeaning(concept.CodeValue, concept.CodingSchemeDesignator, concept.CodeMeaning)

      return (quantity,units)
    except:
      return (None,None)

  def convertStudyDate(self, studyDate):
    """Return a readable study date string """
    if len(studyDate)==8:
      studyDate = studyDate[:4] + '-' + studyDate[4:6] + '-' + studyDate[6:]
    return studyDate


  def sortLoadableSeriesFiles(self, loadable):
    scalarVolumePlugin = slicer.modules.dicomPlugins['DICOMScalarVolumePlugin']()
    svLoadables = scalarVolumePlugin.examine([loadable.files])
    if not len(svLoadables):
      print('Error: failed to parse PET volume!')
      return
    else:
      loadable.files = svLoadables[0].files
      return

  def load(self,loadable):
    loadablePetSeries = self.getLoadablePetSeriesFromRWVMFile( loadable.files[0] )
    return self.loadPetSeries(loadablePetSeries[0])

  def loadPetSeries(self, loadable):
    """Use the conversion factor to load the volume into Slicer"""

    conversionFactor = loadable.slope

    # Create volume node
    imageNode = self.scalarVolumePlugin.loadFilesWithArchetype(loadable.files, loadable.name)
    if imageNode:
      # apply the conversion factor
      multiplier = vtk.vtkImageMathematics()
      multiplier.SetOperationToMultiplyByK()
      multiplier.SetConstantK(float(conversionFactor))
      multiplier.SetInput1Data(imageNode.GetImageData())
      multiplier.Update()
      imageNode.GetImageData().DeepCopy(multiplier.GetOutput())

      # create list of DICOM instance UIDs corresponding to the loaded files
      instanceUIDs = ""
      for dicomFile in loadable.files:
        uid = slicer.dicomDatabase.fileValue(dicomFile,self.tags['sopInstanceUID'])
        if uid == "":
          uid = "Unknown"
        instanceUIDs += uid + " "
      instanceUIDs = instanceUIDs[:-1]  # strip last space

      # get the instance UID for the RWVM object
      derivedItemUID = ""
      try:
        derivedItemUID = slicer.dicomDatabase.fileValue(loadable.rwvFile,self.tags['sopInstanceUID'])
      except AttributeError:
        # no derived items
        pass

      if loadable.quantity:
        imageNode.SetVoxelValueQuantity(loadable.quantity)
      if loadable.units:
        imageNode.SetVoxelValueUnits(loadable.units)

      # Keep references to the PET instances, as these may be needed to
      # establish correspondence between slice annotations and acutal slices,
      # but also keep the RWVM instance UID ... it's confusing, but not sure
      # if there is a better way in Slicer for now
      imageNode.SetAttribute("DICOM.instanceUIDs", instanceUIDs)
      imageNode.SetAttribute("DICOM.RWV.instanceUID", derivedItemUID)

      # automatically select the volume to display
      volumeLogic = slicer.modules.volumes.logic()
      appLogic = slicer.app.applicationLogic()
      selNode = appLogic.GetSelectionNode()
      selNode.SetReferenceActiveVolumeID(imageNode.GetID())
      appLogic.PropagateVolumeSelection()

      # Change display
      displayNode = imageNode.GetVolumeDisplayNode()
      displayNode.SetInterpolate(0)
      if loadable.referencedModality == 'PT':
        radiopharmaceuticalCode = ''
        try:
          radiopharmaceuticalCode = loadable.RadiopharmaceuticalCodeValue
          imageNode.SetAttribute('DICOM.RadiopharmaceuticalCodeValue',radiopharmaceuticalCode)
          print('Found Radiopharmaceutical Code ' + radiopharmaceuticalCode)
        except AttributeError:
          imageNode.SetAttribute('DICOM.RadiopharmaceuticalCodeValue','unknown')
          # use radionuclide info instead
          radionuclideCode = ''
          try:
            radionuclideCode = loadable.RadionuclideCodeValue
            imageNode.SetAttribute('DICOM.RadionuclideCodeValue',radionuclideCode)
            print('Found Radionuclide Code ' + radionuclideCode)
          except AttributeError:
            imageNode.SetAttribute('DICOM.RadionuclideCodeValue','unknown')
        if radiopharmaceuticalCode == 'C-B1031': # FDG
          displayNode.AutoWindowLevelOff()
          displayNode.SetWindowLevel(6,3)
          displayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeInvertedGrey')
        elif radiopharmaceuticalCode == 'C-B1036': # FLT
          displayNode.AutoWindowLevelOff()
          displayNode.SetWindowLevel(4,2)
          displayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeInvertedGrey')
        else: # Default W/L if no info about radiopharmaceutical can be found, often FDG
          displayNode.AutoWindowLevelOff()
          displayNode.SetWindowLevel(6,3)
          displayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeInvertedGrey')
      else:
        displayNode.SetAutoWindowLevel(1)

      # Change name
      name = (loadable.name).replace(' ','_')
      imageNode.SetName(name)

      # create Subject Hierarchy nodes for the loaded series
      self.addSeriesInSubjectHierarchy(loadable,imageNode)

    return imageNode

  def loadPetMultiVolumeSeries(self, loadable):
    """Use the conversion factor to load the volume into Slicer"""

    conversionFactor = loadable.slope

    multiVolumePlugin = slicer.modules.dicomPlugins['MultiVolumeImporterPlugin']()
    mVLoadables = multiVolumePlugin.examine([loadable.files])
    if len(mVLoadables) == 0:
      raise OSError(f"Invalid input for multivolume importer")

    if len(mVLoadables) > 1:
      assert len(mVLoadables) == 2
      mVLoadables = [mV for mV in  mVLoadables if hasattr(mV, 'loadAsVolumeSequence')]
      assert len(mVLoadables) == 1
    mVLoadable = mVLoadables[0]
    # imageNode = multiVolumePlugin.load(mVLoadable)

    mvNode = ''
    try:
      mvNode = mVLoadable.multivolume
    except AttributeError:
      return None

    nFrames = int(mvNode.GetAttribute('MultiVolume.NumberOfFrames'))
    files = mvNode.GetAttribute('MultiVolume.FrameFileList').split(',')
    nFiles = len(files)
    filesPerFrame = int(nFiles/nFrames)
    frames = []

    baseName = mVLoadable.name

    loadAsVolumeSequence = hasattr(mVLoadable, 'loadAsVolumeSequence') and mVLoadable.loadAsVolumeSequence
    if loadAsVolumeSequence:
      volumeSequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode",
        slicer.mrmlScene.GenerateUniqueName(baseName))
      volumeSequenceNode.SetIndexName("")
      volumeSequenceNode.SetIndexUnit("")
      # Transfer all attributes from multivolume node to volume sequence node
      for attrName in mvNode.GetAttributeNames():
        volumeSequenceNode.SetAttribute(attrName, mvNode.GetAttribute(attrName))
    else:
      mvImage = vtk.vtkImageData()
      mvImageArray = None

    scalarVolumePlugin = slicer.modules.dicomPlugins['DICOMScalarVolumePlugin']()
    instanceUIDs = ""
    for file in files:
      uid = slicer.dicomDatabase.fileValue(file,multiVolumePlugin.tags['instanceUID'])
      if uid == "":
        uid = "Unknown"
      instanceUIDs += uid+" "
    instanceUIDs = instanceUIDs[:-1]
    mvNode.SetAttribute("DICOM.instanceUIDs", instanceUIDs)

    progressbar = slicer.util.createProgressDialog(labelText="Loading "+baseName,
                                                   value=0, maximum=nFrames,
                                                   windowModality = qt.Qt.WindowModal)

    try:
      # read each frame into scalar volume
      for frameNumber in range(nFrames):

        progressbar.value = frameNumber
        slicer.app.processEvents()
        if progressbar.wasCanceled:
          break

        sNode = slicer.vtkMRMLVolumeArchetypeStorageNode()
        sNode.ResetFileNameList()

        frameFileList = files[frameNumber*filesPerFrame:(frameNumber+1)*filesPerFrame]
        # sv plugin will sort the filenames by geometric order
        svLoadables = scalarVolumePlugin.examine([frameFileList])

        if len(svLoadables) == 0:
          raise OSError(f"volume frame {frameNumber} is invalid")

        frame = scalarVolumePlugin.load(svLoadables[0])

        # Harden the acquisition transform if there is any
        # (for example due to varying slice spacing)
        # and then remove the transform from the scene
        parentTransformNode = frame.GetParentTransformNode()
        if parentTransformNode:
          frame.HardenTransform()
          slicer.mrmlScene.RemoveNode(parentTransformNode)

        if frame == None or frame.GetImageData() == None:
          raise OSError(f"Volume frame {frameNumber} is invalid - {svLoadables[0].warning}")

        #
        # SCALING
        #
        frame = self.conversion(loadable, frame, conversionFactor, frameFileList)

        if loadAsVolumeSequence:
          # Load into volume sequence

          # volumeSequenceNode.SetDataNodeAtValue would deep-copy the volume frame.
          # To avoid memory reallocation, add an empty node and shallow-copy the contents
          # of the volume frame.

          # Create an empty volume node in the sequence node
          proxyVolume = slicer.mrmlScene.AddNewNodeByClass(frame.GetClassName())
          indexValue = str(frameNumber)
          volumeSequenceNode.SetDataNodeAtValue(proxyVolume, indexValue)
          slicer.mrmlScene.RemoveNode(proxyVolume)

          # Update the data node
          shallowCopy = True
          volumeSequenceNode.UpdateDataNodeAtValue(frame, indexValue, shallowCopy)

        else:
          # Load into multi-volume

          if frameNumber == 0:
            frameImage = frame.GetImageData()
            frameExtent = frameImage.GetExtent()
            frameSize = frameExtent[1]*frameExtent[3]*frameExtent[5]

            mvImage.SetExtent(frameExtent)
            mvImage.AllocateScalars(frame.GetImageData().GetScalarType(), nFrames)

            mvImageArray = vtk.util.numpy_support.vtk_to_numpy(mvImage.GetPointData().GetScalars())

            mvNode.SetScene(slicer.mrmlScene)

            mat = vtk.vtkMatrix4x4()
            frame.GetRASToIJKMatrix(mat)
            mvNode.SetRASToIJKMatrix(mat)
            frame.GetIJKToRASMatrix(mat)
            mvNode.SetIJKToRASMatrix(mat)

          frameImage = frame.GetImageData()
          frameImageArray = vtk.util.numpy_support.vtk_to_numpy(frameImage.GetPointData().GetScalars())

          mvImageArray.T[frameNumber] = frameImageArray

        # Remove temporary volume node
        if frame.GetDisplayNode():
          slicer.mrmlScene.RemoveNode(frame.GetDisplayNode())
        if frame.GetStorageNode():
          slicer.mrmlScene.RemoveNode(frame.GetStorageNode())
        slicer.mrmlScene.RemoveNode(frame)

      if loadAsVolumeSequence:
        # Finalize volume sequence import
        # For user convenience, add a browser node and show the volume in the slice viewer.

        # Add browser node
        sequenceBrowserNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSequenceBrowserNode',
          slicer.mrmlScene.GenerateUniqueName(baseName + " browser"))
        sequenceBrowserNode.SetAndObserveMasterSequenceNodeID(volumeSequenceNode.GetID())
        # If save changes are allowed then proxy nodes are updated using shallow copy, which is much
        # faster for images. Images are usually not modified, so the risk of accidentally modifying
        # data in the sequence is low.
        sequenceBrowserNode.SetSaveChanges(volumeSequenceNode, True)
        # Show frame number in proxy volume node name
        sequenceBrowserNode.SetOverwriteProxyName(volumeSequenceNode, True);

        # Automatically select the volume to display
        imageProxyVolumeNode = sequenceBrowserNode.GetProxyNode(volumeSequenceNode)
        appLogic = slicer.app.applicationLogic()
        selNode = appLogic.GetSelectionNode()
        selNode.SetReferenceActiveVolumeID(imageProxyVolumeNode.GetID())
        appLogic.PropagateVolumeSelection()

        # Show under the right patient/study in subject hierarchy
        self.addSeriesInSubjectHierarchy(mVLoadable, imageProxyVolumeNode)

        # Show sequence browser toolbar
        sequencesModule = slicer.modules.sequences
        if sequencesModule.autoShowToolBar:
          sequencesModule.setToolBarActiveBrowserNode(sequenceBrowserNode)
          sequencesModule.setToolBarVisible(True)
        self.configureDisplayNode(imageProxyVolumeNode, loadable)
      else:
        # Finalize multi-volume import

        mvDisplayNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMultiVolumeDisplayNode')
        mvDisplayNode.SetDefaultColorMap()

        mvNode.SetAndObserveDisplayNodeID(mvDisplayNode.GetID())
        mvNode.SetAndObserveImageData(mvImage)
        mvNode.SetNumberOfFrames(nFrames)
        mvNode.SetName(mVLoadable.name)
        slicer.mrmlScene.AddNode(mvNode)

        # Show under the right patient/study in subject hierarchy
        self.addSeriesInSubjectHierarchy(mVLoadable, mvNode)

        #
        # automatically select the volume to display
        #
        appLogic = slicer.app.applicationLogic()
        selNode = appLogic.GetSelectionNode()
        selNode.SetReferenceActiveVolumeID(mvNode.GetID())
        appLogic.PropagateVolumeSelection()

        # file list is no longer needed - remove the attribute
        mvNode.RemoveAttribute('MultiVolume.FrameFileList')
        self.configureDisplayNode(mvNode, loadable)


    except Exception as e:
      logging.error(f"Failed to read a multivolume: {str(e)}")
      import traceback
      traceback.print_exc()
      mvNode = None

    finally:
      progressbar.close()

    return mvNode


  def configureDisplayNode(self, volumeNode, loadable):
    appLogic = slicer.app.applicationLogic()
    selNode = appLogic.GetSelectionNode()
    displayNode = volumeNode.GetDisplayNode()
    if displayNode is None:
      return  # safety check

    # Disable interpolation
    displayNode.SetInterpolate(0)
    if loadable.referencedModality == 'PT':
      radiopharmaceuticalCode = ''
      try:
        radiopharmaceuticalCode = loadable.RadiopharmaceuticalCodeValue
        volumeNode.SetAttribute('DICOM.RadiopharmaceuticalCodeValue',radiopharmaceuticalCode)
        print('Found Radiopharmaceutical Code ' + radiopharmaceuticalCode)
      except AttributeError:
        volumeNode.SetAttribute('DICOM.RadiopharmaceuticalCodeValue','unknown')
        # use radionuclide info instead
        radionuclideCode = ''
        try:
          radionuclideCode = loadable.RadionuclideCodeValue
          volumeNode.SetAttribute('DICOM.RadionuclideCodeValue',radionuclideCode)
          print('Found Radionuclide Code ' + radionuclideCode)
        except AttributeError:
          volumeNode.SetAttribute('DICOM.RadionuclideCodeValue','unknown')
      if radiopharmaceuticalCode == 'C-B1031': # FDG
        displayNode.AutoWindowLevelOff()
        displayNode.SetWindowLevel(6,3)
        displayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeInvertedGrey')
      elif radiopharmaceuticalCode == 'C-B1036': # FLT
        displayNode.AutoWindowLevelOff()
        displayNode.SetWindowLevel(4,2)
        displayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeInvertedGrey')
      else: # Default W/L if no info about radiopharmaceutical can be found, often FDG
        displayNode.AutoWindowLevelOff()
        displayNode.SetWindowLevel(6,3)
        displayNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeInvertedGrey')
    else:
      displayNode.SetAutoWindowLevel(1)

  def conversion(self, loadable, imageNode, conversionFactor, files):
    # Create volume node
    # imageNode = self.scalarVolumePlugin.loadFilesWithArchetype(loadable.files, loadable.name)
    if imageNode:
      # apply the conversion factor
      multiplier = vtk.vtkImageMathematics()
      multiplier.SetOperationToMultiplyByK()
      multiplier.SetConstantK(float(conversionFactor))
      multiplier.SetInput1Data(imageNode.GetImageData())
      multiplier.Update()
      imageNode.GetImageData().DeepCopy(multiplier.GetOutput())

      # create list of DICOM instance UIDs corresponding to the loaded files
      instanceUIDs = ""
      for dicomFile in files:
        uid = slicer.dicomDatabase.fileValue(dicomFile,self.tags['sopInstanceUID'])
        if uid == "":
          uid = "Unknown"
        instanceUIDs += uid + " "
      instanceUIDs = instanceUIDs[:-1]  # strip last space

      # get the instance UID for the RWVM object
      derivedItemUID = ""
      try:
        derivedItemUID = slicer.dicomDatabase.fileValue(loadable.rwvFile,self.tags['sopInstanceUID'])
      except AttributeError:
        # no derived items
        pass

      if loadable.quantity:
        imageNode.SetVoxelValueQuantity(loadable.quantity)
      if loadable.units:
        imageNode.SetVoxelValueUnits(loadable.units)

      # Keep references to the PET instances, as these may be needed to
      # establish correspondence between slice annotations and acutal slices,
      # but also keep the RWVM instance UID ... it's confusing, but not sure
      # if there is a better way in Slicer for now
      imageNode.SetAttribute("DICOM.instanceUIDs", instanceUIDs)
      imageNode.SetAttribute("DICOM.RWV.instanceUID", derivedItemUID)

      # # automatically select the volume to display
      # volumeLogic = slicer.modules.volumes.logic()
      # appLogic = slicer.app.applicationLogic()
      # selNode = appLogic.GetSelectionNode()
      # selNode.SetReferenceActiveVolumeID(imageNode.GetID())
      # appLogic.PropagateVolumeSelection()
      #
    return imageNode


#
# DICOMRWVMPlugin
#

class DICOMRWVMPlugin:
  """
  This class is the 'hook' for slicer to detect and recognize the plugin
  as a loadable scripted module
  """
  def __init__(self, parent):
    parent.title = "DICOM Real World Value Mapping Plugin"
    parent.categories = ["Developer Tools.DICOM Plugins"]
    parent.contributors = ["Ethan Ulrich (Univ. of Iowa), Andrey Fedorov (BWH)"]
    parent.helpText = """
    Plugin to the DICOM Module to parse and load DICOM series associated with
    Real World Value Mapping objects. Provides options for standardized uptake values.
    No module interface here, only in the DICOM module
    """
    parent.acknowledgementText = """
    This DICOM Plugin was developed by
    Ethan Ulrich, Univ. of Iowa
    and was partially funded by NIH grant U24 CA180918.
    """

    # don't show this module - it only appears in the DICOM module
    parent.hidden = True

    # Add this extension to the DICOM module's list for discovery when the module
    # is created.  Since this module may be discovered before DICOM itself,
    # create the list if it doesn't already exist.
    try:
      slicer.modules.dicomPlugins
    except AttributeError:
      slicer.modules.dicomPlugins = {}
    slicer.modules.dicomPlugins['DICOMRWVMPlugin'] = DICOMRWVMPluginClass

#
# DICOMPETSUVWidget
#

class DICOMPETSUVWidget:
  def __init__(self, parent = None):
    self.parent = parent

  def setup(self):
    # don't display anything for this widget - it will be hidden anyway
    pass

  def enter(self):
    pass

  def exit(self):
    pass
